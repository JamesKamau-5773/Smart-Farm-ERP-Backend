"""Ending employment, and deleting staff records that were created by mistake.

Offboarding keeps the record (payroll, advances and the ledger refer to it),
closes the employee's login and signs out every session. A hard delete is only
allowed for a record nothing else refers to yet.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from app.models.hr import Employee, OffboardingReason
from app.repositories.hr_repo import EmployeeRepository
from app.services.audit_service import record_audit
from app.services.employee_history_service import EmployeeHistoryService
from app.services.staff_access_service import StaffAccessService
from app.utils.api_errors import ApiError
from app.utils.farm_time import farm_today
from app.utils.unit_of_work import unit_of_work


class EmployeeOffboardingService:
    @staticmethod
    def offboard(tenant_id: int, employee_id: int, data: dict, *, actor_id: Optional[int], ip_address=None) -> Employee:
        employee = EmployeeOffboardingService._get(tenant_id, employee_id)
        if employee.end_date is not None:
            raise ApiError('ALREADY_OFFBOARDED', 'This employee has already been offboarded.', 409)

        end_date = EmployeeOffboardingService._end_date(data.get('end_date'), employee)
        reason = str(data.get('offboarding_reason') or data.get('reason') or '').strip().upper()
        if reason not in OffboardingReason.ALL:
            raise ApiError('VALIDATION_ERROR', f"offboarding_reason must be one of: {', '.join(sorted(OffboardingReason.ALL))}.")
        note = (data.get('offboarding_note') or data.get('note') or '').strip() or None
        if reason == OffboardingReason.OTHER and not note:
            raise ApiError('VALIDATION_ERROR', 'offboarding_note is required when the reason is OTHER.')

        balance = Decimal(employee.loan_balance or 0)
        if balance > 0:
            raise ApiError(
                'LOAN_OUTSTANDING',
                f'{employee.full_name} still owes {balance:,.2f} in advances. Record the repayment, '
                'or recover it through a final payroll run, before offboarding.',
                409,
                loan_balance=float(balance),
            )

        before = {'status': employee.status, 'is_active': employee.is_active, 'end_date': None}
        with unit_of_work():
            employee.end_date = end_date
            employee.offboarding_reason = reason
            employee.offboarding_note = note
            employee.offboarded_at = datetime.now(timezone.utc)
            employee.offboarded_by = actor_id
            employee.status = 'INACTIVE'
            employee.is_active = False
            StaffAccessService.revoke(employee)
            record_audit(
                user_id=actor_id,
                action='OFFBOARD_EMPLOYEE',
                entity_type='Employee',
                entity_id=employee.id,
                old_value=before,
                new_value={'status': 'INACTIVE', 'is_active': False, 'end_date': end_date.isoformat(),
                           'offboarding_reason': reason, 'login_disabled': employee.user_id is not None},
                ip_address=ip_address,
            )
        return employee

    @staticmethod
    def delete(tenant_id: int, employee_id: int, *, actor_id: Optional[int], ip_address=None) -> None:
        employee = EmployeeOffboardingService._get(tenant_id, employee_id)
        history = EmployeeHistoryService.kinds_on_record(employee)
        if history:
            raise ApiError(
                'HAS_HISTORY',
                f'{employee.full_name} has {", ".join(history)} on record, so the record cannot be deleted. Offboard them instead.',
                409,
                history=history,
                can_offboard=employee.end_date is None,
            )
        snapshot = {'full_name': employee.full_name, 'id_number': employee.id_number, 'user_id': employee.user_id}
        with unit_of_work():
            StaffAccessService.revoke(employee)
            EmployeeRepository.stage_delete(employee)
            record_audit(
                user_id=actor_id,
                action='DELETE_EMPLOYEE',
                entity_type='Employee',
                entity_id=employee_id,
                old_value=snapshot,
                new_value=None,
                ip_address=ip_address,
            )

    @staticmethod
    def _get(tenant_id: int, employee_id: int) -> Employee:
        employee = EmployeeRepository.get_by_id_for_tenant(employee_id, tenant_id)
        if employee is None:
            raise ApiError('NOT_FOUND', 'Employee not found for this tenant.', 404)
        return employee

    @staticmethod
    def _end_date(value, employee: Employee) -> date:
        if value in (None, ''):
            return farm_today()
        try:
            end_date = date.fromisoformat(str(value))
        except ValueError:
            raise ApiError('VALIDATION_ERROR', 'end_date must be in YYYY-MM-DD format.')
        if end_date > farm_today():
            raise ApiError('VALIDATION_ERROR', 'end_date cannot be in the future. Offboard on or after the last working day.')
        if employee.hire_date and end_date < employee.hire_date:
            raise ApiError('VALIDATION_ERROR', 'end_date cannot be before the hire date.')
        return end_date
